# GME Market Intelligence
Source: Gestore dei Mercati Energetici S.p.A. – [API access and terms](https://www.mercatoelettrico.org/Home/InterfacciaAPI) and [technical guide](https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20251015Manuale_tecnico_API.pdf), §§5.17, 5.19, 5.20.

The public app contains **synthetic examples only**. Standard API terms provide personal/private informational use; obtain written permission for redistribution or commercial use where required. Do not configure credentials on Streamlit Community Cloud, commit data, scrape the website, or expose real data to AI. This is not a source of official applied settlement prices.

For an isolated, authorized private installation only:
1. Request personal credentials from the official GME portal.
2. In a local terminal set `export IGOR_GME_PRIVATE_AUTHORIZED=1`.
3. Run `python -m gasops_app.gme_market prices 2026-10-01 2026-10-31 /path/outside/repo/gme-prices.json --authorized-private-use`. The CLI prompts for credentials without echoing the password. Use `mgs` or `mpl` for their datasets. Maximum 31 days per query, no automatic retry.
4. Start the app bound to loopback (`streamlit run app.py --server.address 127.0.0.1`); in Mercato e previsioni → Mercato gas GME import the JSON in the matching view. Unset the flag before any shared deployment.

The decoder accepts only the documented JSON ZIP envelope with a single JSON member and the supported list-of-records shape. Real authenticated response shape, publication coverage, units for volume fields and duplicate/session conventions still need verification with an authorized sample. Conflicting/ambiguous rows are rejected, never guessed. The study price calculator reuses the existing CdR XCII motor; title volume and semester percentage must be supplied independently. MGS/MPL results remain separate. No real data is automatically fed to briefing, prices, AI or settlement.
