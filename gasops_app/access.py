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


def authorized_identity():
    """Verify an allowlisted identity independently of the active layout."""
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


def private_access():
    return profile() == PRIVATE and authorized_identity()


def login_configured():
    from importlib.util import find_spec
    if not (os.getenv("GASOPS_AUTH_ISSUER", "").strip()
            and os.getenv("GASOPS_PRIVATE_SUBJECTS", "").strip() and find_spec("authlib")):
        return False
    import streamlit as st
    try:
        return bool(st.secrets.get("auth"))
    except (FileNotFoundError, KeyError, ValueError):
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
    if login_configured():
        if st.button("Accedi", type="primary"):
            st.login()
    else:
        st.caption("Accesso privato disabilitato: configurazione di autenticazione incompleta.")
    st.stop()
