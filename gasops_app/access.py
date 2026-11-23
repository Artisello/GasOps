"""Server-owned deployment profile and fail-closed private authorization.

The legacy app mode selects a layout, never permissions. No decision reads
query parameters or session_state. Streamlit verifies the OIDC identity;
the operator must separately allow its issuer and immutable subject.
"""
import os
from math import isfinite
from time import time

PUBLIC = "public_demo"
PRIVATE = "private_workbench"
TEST = "test"


def profile():
    value = os.getenv("GASOPS_PROFILE", PUBLIC).strip().lower()
    return value if value in (PUBLIC, PRIVATE, TEST) else PUBLIC


def demo_layout():
    return profile() != PRIVATE and os.getenv("GASOPS_APP_MODE", "demo").strip().lower() != "workbench"


def private_access():
    if profile() != PRIVATE:
        return False
    import streamlit as st
    try:
        user = st.user
        issuer = os.getenv("GASOPS_AUTH_ISSUER", "").strip()
        subjects = {s.strip() for s in os.getenv("GASOPS_PRIVATE_SUBJECTS", "").split(",") if s.strip()}
        # Expiry is checked again on each action, beyond Streamlit's identity
        # cookie lifetime. Missing/malformed claims never grant access.
        expires = float(user.get("exp", 0))
        return bool(issuer and subjects and user.is_logged_in and user.get("iss") == issuer
                    and user.get("sub") in subjects and isfinite(expires) and expires > time())
    except (AttributeError, KeyError, TypeError, ValueError, FileNotFoundError):
        return False


def require_private():
    if not private_access():
        raise PermissionError("Operazione riservata: autenticazione e autorizzazione richieste.")


def document_directory(root):
    """Only explicitly public repository PDFs may be shared by the demo."""
    if private_access():
        from pathlib import Path
        return Path(os.getenv("GASOPS_PDF_DIR") or root / "data" / "regulatory"), False
    return root / "data" / "public-regulatory", True


def guard_application():
    if profile() != PRIVATE or private_access():
        return
    import streamlit as st
    st.title("Accesso riservato")
    st.info("Questo Workbench richiede un account autorizzato.")
    try:
        from importlib.util import find_spec
        configured = bool(st.secrets.get("auth") and os.getenv("GASOPS_AUTH_ISSUER")
                          and os.getenv("GASOPS_PRIVATE_SUBJECTS") and find_spec("authlib"))
    except (FileNotFoundError, KeyError):
        configured = False
    if configured:
        if st.button("Accedi", type="primary"):
            st.login()
    else:
        st.caption("Accesso privato disabilitato: configurazione di autenticazione incompleta.")
    st.stop()
