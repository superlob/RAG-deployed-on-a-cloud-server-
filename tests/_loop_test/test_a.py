import asyncio
import pytest
pytestmark = pytest.mark.asyncio(loop_scope="session")
async def test_loop_a(): print("A", id(asyncio.get_running_loop()))
