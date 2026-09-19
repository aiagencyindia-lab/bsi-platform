"""Create one organization, workspace and API key. Prints the key once."""

import hashlib
import secrets
import sys

from bsi_core import models as m
from bsi_core.db import owner_engine
from sqlalchemy.orm import Session


def main(name: str) -> None:
    token = "bsi_" + secrets.token_hex(32)
    with Session(owner_engine()) as s, s.begin():
        org = m.Organization(name=name)
        s.add(org)
        s.flush()
        ws = m.Workspace(org_id=org.id, name="Default")
        s.add(ws)
        s.flush()
        s.add(
            m.ApiKey(
                org_id=org.id,
                workspace_id=ws.id,
                hashed_key=hashlib.sha256(token.encode()).hexdigest(),
            )
        )
        print(f"org_id:  {org.id}")
    print(f"api key: {token}   (shown once; store it now)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Dev Org")
