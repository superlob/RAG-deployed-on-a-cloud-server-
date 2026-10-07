import asyncio
import pytest
pytestmark = pytest.mark.asyncio(loop_scope="session")
async def test_loop_b(): print("B", id(asyncio.get_running_loop()))
