import pytest

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def postgres_container():
    """
    Starts a real PostgreSQL container for tests.
    Session scope: a single container for the entire test suite.
    """
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
async def test_engine(postgres_container):
    """
    SQLAlchemy Engine pointing to the test container.
    Creates all tables via Base.metadata.create_all.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.repositories.models import Base

    # Converts testcontainers URL to asyncpg
    url = (
        postgres_container.get_connection_url()
        .replace("postgresql://", "postgresql+asyncpg://")
        .replace("psycopg2", "asyncpg")
    )

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """
    Test database session isolated by SAVEPOINT.
    
    Binds the AsyncSession to an open transaction on a connection,
    using `join_transaction_mode="create_savepoint"` to ensure that
    application `session.commit()` only commits the savepoint, 
    preserving the outer transaction which is rolled back here.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with test_engine.connect() as conn:
        trans = await conn.begin()
        
        async with AsyncSession(
            bind=conn, 
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session:
            yield session

        await trans.rollback()
@pytest.fixture
async def app_for_tests():
    """
    FastAPI instance with lifespan disabled for tests.
    Patches load_secrets and setup_tracing to avoid connecting to external services.
    """
    from unittest.mock import patch, AsyncMock
    from app.main import app

    with patch("app.config.settings.load_secrets", new_callable=AsyncMock):
        with patch("app.main.setup_tracing"):
            yield app


@pytest.fixture
async def async_client(app_for_tests, db_session, mock_requester_client):
    """
    httpx AsyncClient with dependency overrides injected.
    Overrides get_session and _get_requester_client.
    """
    from httpx import AsyncClient, ASGITransport
    from app.repositories.database import get_session
    from app.api.routes import _get_requester_client

    async def override_get_session():
        yield db_session

    app_for_tests.dependency_overrides[get_session] = override_get_session
    app_for_tests.dependency_overrides[_get_requester_client] = (
        lambda: mock_requester_client
    )

    async with AsyncClient(
        transport=ASGITransport(app=app_for_tests),
        base_url="http://test",
    ) as client:
        yield client

    app_for_tests.dependency_overrides.clear()


@pytest.fixture
def mock_requester_client():
    """
    Mock for RequesterClientPort.
    By default, validate_requester returns True (valid requester).
    """
    from unittest.mock import AsyncMock
    from app.domain.ports import RequesterClientPort

    mock = AsyncMock(spec=RequesterClientPort)
    mock.validate_requester.return_value = True
    return mock


@pytest.fixture
def sample_order_payload():
    """
    Returns a standard order payload for testing.
    """
    return {
        "external_order_id": "ORD-TEST-001",
        "requester_id": "REQ-TEST-001",
        "description": "Test order for system validation",
    }
