from anydi import Provider


def test_provider_basic():
    """Test Provider with basic arguments."""
    provider = Provider(dependency_type=int, factory=lambda: 42, scope="singleton")

    assert provider.dependency_type is int
    assert provider.scope == "singleton"
