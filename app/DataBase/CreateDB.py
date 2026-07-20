"""Create tables and seed one test user with one car.

Run once:  python create_db.py
Safe to re-run: it skips seeding if the user already exists.
"""

import asyncio

from sqlalchemy import select

from DB import SessionLocal, init_db
from Models import User, Vehicle
from Security import hash_password

TEST_EMAIL = "test@ampere.com"
TEST_PASSWORD = "test1234"
TEST_VIN = "TESTVIN123"


async def main() -> None:
    await init_db()
    print("tables created (or already existed)")

    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == TEST_EMAIL))
        if existing:
            print(f"user {TEST_EMAIL} already exists, nothing to seed")
            return

        user = User(email=TEST_EMAIL, password_hash=hash_password(TEST_PASSWORD))
        session.add(user)

        # flush() sends the INSERT so user.id is populated, without committing.
        # We need the id for the foreign key below.
        await session.flush()

        session.add(Vehicle(vin=TEST_VIN, name="Test Clio", owner_id=user.id))

        # Nothing above is permanent until this line -- both inserts land
        # together or not at all. That's the transaction.
        await session.commit()

        print(f"seeded user {TEST_EMAIL} / {TEST_PASSWORD}")
        print(f"seeded vehicle {TEST_VIN} owned by {user.id}")


if __name__ == "__main__":
    asyncio.run(main())