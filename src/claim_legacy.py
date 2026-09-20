"""Assign unclaimed measurements to an identity that has already signed in."""

import argparse
import asyncio
import sys

from sqlalchemy import func, select, update

from src.core.config import get_settings
from src.core.database import Database
from src.models.user import ExternalIdentity
from src.models.weight_log import WeightLog


async def claim(subject: str, apply: bool) -> int:
    settings = get_settings()
    if not settings.clerk_issuer:
        raise ValueError("Configure CLERK_ISSUER before claiming measurements")
    database = Database(settings)
    try:
        async with database.session_factory() as session, session.begin():
            identity = await session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.issuer == settings.clerk_issuer,
                    ExternalIdentity.subject == subject,
                )
            )
            if identity is None:
                raise ValueError(
                    "Identity not found: sign in and open the weight page first"
                )
            count = await session.scalar(
                select(func.count())
                .select_from(WeightLog)
                .where(WeightLog.user_id.is_(None))
            )
            if apply:
                await session.execute(
                    update(WeightLog)
                    .where(WeightLog.user_id.is_(None))
                    .values(user_id=identity.user_id)
                )
            return count or 0
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subject",
        required=True,
        help="Verified Clerk user ID from the Dashboard (not an email)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply assignment; default is a count-only preview",
    )
    args = parser.parse_args()
    with asyncio.Runner(
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
    ) as runner:
        count = runner.run(claim(args.subject, args.apply))
    print(
        f"{'Assigned' if args.apply else 'Would assign'} {count} unclaimed measurements"
    )


if __name__ == "__main__":
    main()
