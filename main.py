from update_team import update
import asyncio
import os

if __name__ == "__main__":
    email="conor.aspell@ucdconnect.ie"
    password="team_mattata"
    user_id="4340827"
    # email=os.environ.get('EMAIL')
    # password=os.environ.get('PASSWORD')
    # user_id=os.environ.get('USER_ID')
    asyncio.run(update(email, password,user_id))