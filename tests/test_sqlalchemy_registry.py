"""Registry and RegistryMixin tests."""

from types import SimpleNamespace
from uuid import UUID  # noqa: F401  # pylint: disable=unused-import

import pytest

from coaster.sqlalchemy import BaseMixin
from coaster.sqlalchemy.registry import Registry

from .test_sqlalchemy_models import db

# --- Fixtures -------------------------------------------------------------------------


@pytest.fixture()
def CallableRegistry():  # noqa: N802
    """Callable registry with a positional parameter."""

    class CallableRegistry:
        registry = Registry()

    return CallableRegistry


@pytest.fixture()
def PropertyRegistry():  # noqa: N802
    """Registry with property and a positional parameter."""

    class PropertyRegistry:
        registry = Registry(property=True)

    return PropertyRegistry


@pytest.fixture()
def CachedPropertyRegistry():  # noqa: N802
    """Registry with cached property and a positional parameter."""

    class CachedPropertyRegistry:
        registry = Registry(cached_property=True)

    return CachedPropertyRegistry


@pytest.fixture()
def CallableParamRegistry():  # noqa: N802
    """Callable registry with a keyword parameter."""

    class CallableParamRegistry:
        registry = Registry('kwparam')

    return CallableParamRegistry


@pytest.fixture()
def PropertyParamRegistry():  # noqa: N802
    """Registry with property and a keyword parameter."""

    class PropertyParamRegistry:
        registry = Registry('kwparam', property=True)

    return PropertyParamRegistry


@pytest.fixture()
def CachedPropertyParamRegistry():  # noqa: N802
    """Registry with cached property and a keyword parameter."""

    class CachedPropertyParamRegistry:
        registry = Registry('kwparam', cached_property=True)

    return CachedPropertyParamRegistry


@pytest.fixture()
def all_registry_hosts(
    CallableRegistry,  # noqa: N803
    PropertyRegistry,
    CachedPropertyRegistry,
    CallableParamRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """All test registries as a list."""
    return [
        CallableRegistry,
        PropertyRegistry,
        CachedPropertyRegistry,
        CallableParamRegistry,
        PropertyParamRegistry,
        CachedPropertyParamRegistry,
    ]


@pytest.fixture(scope='module')
def registry_member():
    """Test registry member function."""

    def member(pos=None, kwparam=None):
        pass

    return member


@pytest.fixture(scope='session')
def registrymixin_models():
    """Fixtures for RegistryMixin tests."""
    # We have two sample models and two registered items to test that
    # the registry is unique to each model and is not a global registry
    # in the base RegistryMixin class.

    # Sample model 1
    class RegistryTest1(BaseMixin, db.Model):
        """Registry test model 1."""

        __tablename__ = 'registry_test1'

    # Sample model 2
    class RegistryTest2(BaseMixin, db.Model):
        """Registry test model 2."""

        __tablename__ = 'registry_test2'

    # Sample registered item (form or view) 1
    class RegisteredItem1:
        """Registered item 1."""

        def __init__(self, obj=None):
            """Init class."""
            self.obj = obj

    # Sample registered item 2
    @RegistryTest2.views('test')
    class RegisteredItem2:
        """Registered item 2."""

        def __init__(self, obj=None):
            """Init class."""
            self.obj = obj

    # Sample registered item 3
    @RegistryTest1.features('is1')
    @RegistryTest2.features()
    def is1(obj):
        """Assert object is instance of RegistryTest1."""
        return isinstance(obj, RegistryTest1)

    RegistryTest1.views.test = RegisteredItem1

    return SimpleNamespace(**locals())


# --- Tests ----------------------------------------------------------------------------

# --- Creating a registry


def test_registry_set_name():
    """Registry's __set_name__ gets called."""
    # Registry has no name unless added to a class
    assert Registry()._name is None

    class RegistryUser:
        reg1 = Registry()
        reg2 = Registry()

    assert RegistryUser.reg1._name == 'reg1'
    assert RegistryUser.reg2._name == 'reg2'


def test_registry_reuse_error():
    """Registries cannot be reused under different names."""
    # Registry raises TypeError from __set_name__, but Python recasts as RuntimeError
    with pytest.raises(RuntimeError):

        class RegistryUser:
            a = b = Registry()


def test_registry_reuse_okay():
    """Registries be reused with the same name under different hosts."""
    reusable = Registry()

    assert reusable._name is None

    class HostA:
        registry = reusable

    assert HostA.registry._name == 'registry'

    class HostB:
        registry = reusable

    assert HostB.registry._name == 'registry'
    assert HostA.registry is HostB.registry
    assert HostA.registry is reusable


def test_registry_param_type():
    """Registry's param must be string or None."""
    r = Registry()
    assert r._param is None
    r = Registry('')
    assert r._param is None
    r = Registry(1)
    assert r._param == '1'
    r = Registry('obj')
    assert r._param == 'obj'
    r = Registry(param='foo')
    assert r._param == 'foo'


def test_registry_property_cached_property():
    """A registry can have property or cached_property set, but not both."""
    r = Registry()
    assert r._default_property is False
    assert r._default_cached_property is False

    r = Registry(property=True)
    assert r._default_property is True
    assert r._default_cached_property is False

    r = Registry(cached_property=True)
    assert r._default_property is False
    assert r._default_cached_property is True

    with pytest.raises(TypeError):
        Registry(property=True, cached_property=True)


# --- Populating a registry


def test_add_to_registry(
    CallableRegistry,  # noqa: N803
    PropertyRegistry,
    CachedPropertyRegistry,
    CallableParamRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """A member can be added to registries and accessed as per registry settings."""

    @CallableRegistry.registry()
    @PropertyRegistry.registry()
    @CachedPropertyRegistry.registry()
    @CallableParamRegistry.registry()
    @PropertyParamRegistry.registry()
    @CachedPropertyParamRegistry.registry()
    def member(pos=None, kwparam=None):
        return (pos, kwparam)

    callable_host = CallableRegistry()
    property_host = PropertyRegistry()
    cached_property_host = CachedPropertyRegistry()
    callable_param_host = CallableParamRegistry()
    property_param_host = PropertyParamRegistry()
    cached_property_param_host = CachedPropertyParamRegistry()

    assert callable_host.registry.member(1) == (callable_host, 1)
    assert property_host.registry.member == (property_host, None)
    assert cached_property_host.registry.member == (cached_property_host, None)
    assert callable_param_host.registry.member(1) == (1, callable_param_host)
    assert property_param_host.registry.member == (None, property_param_host)
    assert cached_property_param_host.registry.member == (
        None,
        cached_property_param_host,
    )


def test_property_cache_mismatch(
    PropertyRegistry, CachedPropertyRegistry  # noqa: N803
):
    """A registry's default setting must be explicitly turned off if conflicting."""
    with pytest.raises(TypeError):

        @PropertyRegistry.registry(cached_property=True)
        def member1(pos=None, kwparam=None):
            return (pos, kwparam)

    with pytest.raises(TypeError):

        @CachedPropertyRegistry.registry(property=True)
        def member2(pos=None, kwparam=None):
            return (pos, kwparam)

    @PropertyRegistry.registry(cached_property=True, property=False)
    @CachedPropertyRegistry.registry(property=True, cached_property=False)
    def member(pos=None, kwparam=None):
        return (pos, kwparam)


def test_add_to_registry_host(
    CallableRegistry,  # noqa: N803
    PropertyRegistry,
    CachedPropertyRegistry,
    CallableParamRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """A member can be added as a function, overriding default settings."""

    @CallableRegistry.registry()
    @PropertyRegistry.registry(property=False)
    @CachedPropertyRegistry.registry(cached_property=False)
    @CallableParamRegistry.registry()
    @PropertyParamRegistry.registry(property=False)
    @CachedPropertyParamRegistry.registry(cached_property=False)
    def member(pos=None, kwparam=None):
        return (pos, kwparam)

    callable_host = CallableRegistry()
    property_host = PropertyRegistry()
    cached_property_host = CachedPropertyRegistry()
    callable_param_host = CallableParamRegistry()
    property_param_host = PropertyParamRegistry()
    cached_property_param_host = CachedPropertyParamRegistry()

    assert callable_host.registry.member(1) == (callable_host, 1)
    assert property_host.registry.member(2) == (property_host, 2)
    assert cached_property_host.registry.member(3) == (cached_property_host, 3)
    assert callable_param_host.registry.member(4) == (4, callable_param_host)
    assert property_param_host.registry.member(5) == (5, property_param_host)
    assert cached_property_param_host.registry.member(6) == (
        6,
        cached_property_param_host,
    )


def test_add_to_registry_property(
    CallableRegistry,  # noqa: N803
    PropertyRegistry,
    CachedPropertyRegistry,
    CallableParamRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """A member can be added as a property, overriding default settings."""

    @CallableRegistry.registry(property=True)
    @PropertyRegistry.registry(property=True)
    @CachedPropertyRegistry.registry(property=True, cached_property=False)
    @CallableParamRegistry.registry(property=True)
    @PropertyParamRegistry.registry(property=True)
    @CachedPropertyParamRegistry.registry(property=True, cached_property=False)
    def member(pos=None, kwparam=None):
        return (pos, kwparam)

    callable_host = CallableRegistry()
    property_host = PropertyRegistry()
    cached_property_host = CachedPropertyRegistry()
    callable_param_host = CallableParamRegistry()
    property_param_host = PropertyParamRegistry()
    cached_property_param_host = CachedPropertyParamRegistry()

    assert callable_host.registry.member == (callable_host, None)
    assert property_host.registry.member == (property_host, None)
    assert cached_property_host.registry.member == (cached_property_host, None)
    assert callable_param_host.registry.member == (None, callable_param_host)
    assert property_param_host.registry.member == (None, property_param_host)
    assert cached_property_param_host.registry.member == (
        None,
        cached_property_param_host,
    )


def test_add_to_registry_cached_property(
    CallableRegistry,  # noqa: N803
    PropertyRegistry,
    CachedPropertyRegistry,
    CallableParamRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """A member can be added as a property, overriding default settings."""

    @CallableRegistry.registry(property=True)
    @PropertyRegistry.registry(property=True)
    @CachedPropertyRegistry.registry(property=True, cached_property=False)
    @CallableParamRegistry.registry(property=True)
    @PropertyParamRegistry.registry(property=True)
    @CachedPropertyParamRegistry.registry(property=True, cached_property=False)
    def member(pos=None, kwparam=None):
        return (pos, kwparam)

    callable_host = CallableRegistry()
    property_host = PropertyRegistry()
    cached_property_host = CachedPropertyRegistry()
    callable_param_host = CallableParamRegistry()
    property_param_host = PropertyParamRegistry()
    cached_property_param_host = CachedPropertyParamRegistry()

    assert callable_host.registry.member == (callable_host, None)
    assert property_host.registry.member == (property_host, None)
    assert cached_property_host.registry.member == (cached_property_host, None)
    assert callable_param_host.registry.member == (None, callable_param_host)
    assert property_param_host.registry.member == (None, property_param_host)
    assert cached_property_param_host.registry.member == (
        None,
        cached_property_param_host,
    )


def test_add_to_registry_custom_name(all_registry_hosts, registry_member):
    """Members can be added to a registry with a custom name."""
    assert registry_member.__name__ == 'member'
    for host in all_registry_hosts:
        # Mock decorator call
        host.registry('custom')(registry_member)
        # This adds the member under the custom name
        assert host.registry.custom is registry_member
        # The default name of the function is not present...
        with pytest.raises(AttributeError):
            assert host.registry.member is registry_member
        # ... but can be added
        host.registry()(registry_member)
        assert host.registry.member is registry_member


def test_add_to_registry_underscore(all_registry_hosts, registry_member):
    """Registry member names cannot start with an underscore."""
    for host in all_registry_hosts:
        with pytest.raises(ValueError):
            host.registry('_new_member')(registry_member)


def test_add_to_registry_dupe(all_registry_hosts, registry_member):
    """Registry member names cannot be duplicates of an existing name."""
    for host in all_registry_hosts:
        host.registry()(registry_member)
        with pytest.raises(ValueError):
            host.registry()(registry_member)

        host.registry('custom')(registry_member)
        with pytest.raises(ValueError):
            host.registry('custom')(registry_member)


def test_cached_properties_are_cached(
    PropertyRegistry,  # noqa: N803
    CachedPropertyRegistry,
    PropertyParamRegistry,
    CachedPropertyParamRegistry,
):
    """Cached properties are truly cached."""

    # Register registry member
    @PropertyRegistry.registry()
    @CachedPropertyRegistry.registry()
    @PropertyParamRegistry.registry()
    @CachedPropertyParamRegistry.registry()
    def member(pos=None, kwparam=None):
        return [pos, kwparam]  # Lists are different each call

    property_host = PropertyRegistry()
    cached_property_host = CachedPropertyRegistry()
    property_param_host = PropertyParamRegistry()
    cached_property_param_host = CachedPropertyParamRegistry()

    # The properties and cached properties work
    assert property_host.registry.member == [property_host, None]
    assert cached_property_host.registry.member == [cached_property_host, None]
    assert property_param_host.registry.member == [None, property_param_host]
    assert cached_property_param_host.registry.member == [
        None,
        cached_property_param_host,
    ]

    # The properties and cached properties return equal values on each access
    assert property_host.registry.member == property_host.registry.member
    assert cached_property_host.registry.member == cached_property_host.registry.member
    assert property_param_host.registry.member == property_param_host.registry.member
    assert (
        cached_property_param_host.registry.member
        == cached_property_param_host.registry.member
    )

    # Only the cached properties return the same value every time
    assert property_host.registry.member is not property_host.registry.member
    assert cached_property_host.registry.member is cached_property_host.registry.member
    assert (
        property_param_host.registry.member is not property_param_host.registry.member
    )
    assert (
        cached_property_param_host.registry.member
        is cached_property_param_host.registry.member
    )


# TODO:
# test_registry_member_cannot_be_called_clear_cache
# test_multiple_positional_and_keyword_arguments
# test_registry_iter
# test_registry_members_must_be_callable
# test_add_by_directly_sticking_in
# test_instance_registry_is_cached
# test_clear_cache_for
# test_clear_cache
# test_registry_mixin_config
# test_registry_mixin_subclasses

# --- RegistryMixin tests --------------------------------------------------------------


def test_access_item_from_class(registrymixin_models):
    """Registered items are available from the model class."""
    assert (
        registrymixin_models.RegistryTest1.views.test
        is registrymixin_models.RegisteredItem1
    )
    assert (
        registrymixin_models.RegistryTest2.views.test
        is registrymixin_models.RegisteredItem2
    )
    assert (
        registrymixin_models.RegistryTest1.views.test
        is not registrymixin_models.RegisteredItem2
    )
    assert (
        registrymixin_models.RegistryTest2.views.test
        is not registrymixin_models.RegisteredItem1
    )
    assert registrymixin_models.RegistryTest1.features.is1 is registrymixin_models.is1
    assert registrymixin_models.RegistryTest2.features.is1 is registrymixin_models.is1


def test_access_item_class_from_instance(registrymixin_models):
    """Registered items are available from the model instance."""
    r1 = registrymixin_models.RegistryTest1()
    r2 = registrymixin_models.RegistryTest2()
    # When accessed from the instance, we get a partial that resembles
    # the wrapped item, but is not the item itself.
    assert r1.views.test is not registrymixin_models.RegisteredItem1
    assert r1.views.test.func is registrymixin_models.RegisteredItem1
    assert r2.views.test is not registrymixin_models.RegisteredItem2
    assert r2.views.test.func is registrymixin_models.RegisteredItem2
    assert r1.features.is1 is not registrymixin_models.is1
    assert r1.features.is1.func is registrymixin_models.is1
    assert r2.features.is1 is not registrymixin_models.is1
    assert r2.features.is1.func is registrymixin_models.is1


def test_access_item_instance_from_instance(registrymixin_models):
    """Registered items can be instantiated from the model instance."""
    r1 = registrymixin_models.RegistryTest1()
    r2 = registrymixin_models.RegistryTest2()
    i1 = r1.views.test()
    i2 = r2.views.test()

    assert isinstance(i1, registrymixin_models.RegisteredItem1)
    assert isinstance(i2, registrymixin_models.RegisteredItem2)
    assert not isinstance(i1, registrymixin_models.RegisteredItem2)
    assert not isinstance(i2, registrymixin_models.RegisteredItem1)
    assert i1.obj is r1
    assert i2.obj is r2
    assert i1.obj is not r2
    assert i2.obj is not r1


def test_features(registrymixin_models):
    """The features registry can be used for feature tests."""
    r1 = registrymixin_models.RegistryTest1()
    r2 = registrymixin_models.RegistryTest2()

    assert r1.features.is1() is True
    assert r2.features.is1() is False
