"""One bounded, opt-in live check. No credentials, no raw response bodies."""
from datetime import timedelta
import json

import requests

from gasops_app.entsog import URL, _last_completed, parse_month, query_params
from gasops_app.models import utc_now
from gasops_app.public_data import SourceSchemaError


def main():
    now=utc_now()
    last=_last_completed(now)-timedelta(days=2)
    first=last-timedelta(days=6)
    print(f"ENTSOG probe: {first} through {last}; 3 known points.")
    try:
        with requests.get(URL,params=query_params(first,last),timeout=(5,30),stream=True) as response:
            print("HTTP",response.status_code)
            response.raise_for_status()
            body=bytearray()
            for chunk in response.iter_content(16384):
                body.extend(chunk)
                if len(body)>1_000_000:
                    raise SourceSchemaError("payload exceeds 1 MB")
        payload=json.loads(body.decode("utf-8-sig"))
        if isinstance(payload,dict):
            items=payload.get("operationalData",payload.get("operationaldatas"))
            meta=payload.get("meta")
            if isinstance(items,list):
                print("Records:",len(items))
                if items and isinstance(items[0],dict):
                    print("Required fields present:", sorted(set(items[0]) & {"operatorKey","pointKey","directionKey","periodType","periodFrom","periodTo","unit","value","indicator"}))
            if isinstance(meta,dict):
                print("Numeric metadata:",{k:meta[k] for k in ("count","total","offset","limit")
                      if isinstance(meta.get(k),int)})
        parsed=parse_month(payload,first,last,now)
        print("Parser validated the response. Distinct dates:",len(parsed.flags))
        print("Complete gas days:",
              sum(all(parsed.values.get((d,f)) is not None for f in ("distribution_gwh","power_gwh","industry_gwh"))
                  for d in parsed.flags))
    except SourceSchemaError as exc:
        print("Validation:",str(exc))
        return 1
    except (requests.RequestException,ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:
        print("Probe failed:",type(exc).__name__)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
