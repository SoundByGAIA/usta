import pytest

from fake_endpoint import FakeEndpoint


@pytest.fixture
def endpoint():
    ep = FakeEndpoint()
    yield ep
    ep.close()
