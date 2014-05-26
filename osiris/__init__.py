import logging
import os
import ConfigParser

from pyramid.settings import asbool
from pyramid.config import Configurator
from pyramid.exceptions import ConfigurationError
from pyramid_who.whov2 import WhoV2AuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.authentication import AuthTktAuthenticationPolicy

log = logging.getLogger(__name__)

import pkg_resources

try:
    pkg_resources.get_distribution('pyramid_ldap')
except pkg_resources.DistributionNotFound:
    HAS_PYRAMID_LDAP = False
else:
    HAS_PYRAMID_LDAP = True
    import ldap
    from pyramid_ldap import groupfinder
    from pyramid_ldap import get_ldap_connector


def default_setup(config):
    from pyramid.session import UnencryptedCookieSessionFactoryConfig

    log.info('Using an unencrypted cookie-based session. This can be '
             'changed by pointing the "osiris.setup" setting at a different '
             'function for configuring the session factory and other possible '
             'authentication backends, e.g pyramid_ldap.')

    settings = config.registry.settings
    secret = settings.get('osiris.session.secret')
    cookie_name = settings.get('osiris.session.cookie_name',
                               'osiris.session')
    if secret is None:
        log.warn('Configuring unencrypted cookie-based session with a '
                 'random secret which will invalidate old cookies when '
                 'restarting the app.')
        secret = ''.join('%02x' % ord(x) for x in os.urandom(16))
        log.info('autogenerated session secret: %s', secret)
    factory = UnencryptedCookieSessionFactoryConfig(
        secret, cookie_name=cookie_name)

    config.set_session_factory(factory)

    identifier_id = 'auth_tkt'
    ldap_enabled = asbool(settings.get('osiris.ldap_enabled'))
    who_enabled = asbool(settings.get('osiris.who_enabled'))

    if HAS_PYRAMID_LDAP and ldap_enabled:
        config.include('pyramid_ldap')
        authn_policy = AuthTktAuthenticationPolicy(identifier_id, callback=groupfinder)
        authz_policy = ACLAuthorizationPolicy()

        # parse ldap.ini
        ldapconfig = ConfigParser.RawConfigParser()
        ldapconfig.read(settings.get('osiris.ldapconfig'))

        config.ldap_setup(ldapconfig.get('ldap', 'server'),
                          bind=ldapconfig.get('ldap', 'userbind'),
                          passwd=ldapconfig.get('ldap', 'password')
                          )

        config.ldap_set_login_query(base_dn=ldapconfig.get('ldap', 'userbasedn'),
                                    filter_tmpl=ldapconfig.get('ldap', 'userfilter'),
                                    scope=getattr(ldap, ldapconfig.get('ldap', 'userscope')),
                                    )

        config.ldap_set_groups_query(base_dn=ldapconfig.get('ldap', 'groupbasedn'),
                                     filter_tmpl=ldapconfig.get('ldap', 'groupfilter'),
                                     scope=getattr(ldap, ldapconfig.get('ldap', 'groupscope')),
                                     cache_period=ldapconfig.get('ldap', 'groupcache'),
                                     )

    if who_enabled:
        whoconfig = settings['osiris.whoconfig']

        authn_policy = WhoV2AuthenticationPolicy(whoconfig, identifier_id)
        authz_policy = ACLAuthorizationPolicy()

    config.set_authentication_policy(authn_policy)
    config.set_authorization_policy(authz_policy)


def includeme(config):
    """Configuration method to make a pyramid app an osiris enabled one."""
    settings = config.registry.settings

    # setup application
    setup = settings.get('osiris.setup', default_setup)
    if setup:
        config.include(setup)

    # setup backing storage
    store = settings.get('osiris.store')
    if store is None:
        raise ConfigurationError(
            'invalid setting osiris.store: {0}'.format(store))
    config.include(store)

    # add the views
    config.add_route('default_view', '/')
    config.scan(__name__)


def make_app(**settings):
    config = Configurator(settings=settings)
    config.include(includeme)
    return config.make_wsgi_app()


def make_osiris_app(global_conf, **settings):
    """Construct a complete WSGI app ready to serve by Paste

    Example INI file:

    .. code-block:: ini

        [server:main]
        use = egg:Paste#http
        host = 0.0.0.0
        port = 80

        [composite:main]
        use = egg:Paste#urlmap
        / = YOURAPP
        /oauth2 = osiris

        [app:osiris]
        use = egg:osiris

        [app:YOURAPP]
        use = egg:YOURAPP
        full_stack = true
        static_files = true

    """
    return make_app(**settings)
