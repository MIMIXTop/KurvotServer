from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def migrate_legacy_user_roles(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "UPDATE auth_users "
            "SET user_role = 'teacher' "
            "WHERE lower(user_role) IN ('papik', 'student')"
        )
    )
    await connection.execute(
        text(
            "UPDATE auth_users "
            "SET user_role = lower(user_role) "
            "WHERE upper(user_role) IN ('TEACHER', 'ADMIN')"
        )
    )
