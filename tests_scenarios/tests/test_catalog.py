"""Tests for tests_scenarios.catalog: enums, Scenario, CORE, and expand()."""
from tests_scenarios.catalog import CORE, Arch, Auth, Db, Proxy, Scenario, expand


def test_core_covers_every_db_auth_proxy_and_armv7():
    dbs = {s.db for s in CORE}
    assert dbs == {Db.SQLITE, Db.POSTGRES, Db.MARIADB, Db.COCKROACH}
    assert {s.auth for s in CORE} >= {Auth.NONE, Auth.TOKEN, Auth.USERS}
    assert {s.proxy for s in CORE} >= {Proxy.NGINX, Proxy.TRAEFIK, Proxy.CADDY}
    assert any(s.arch is Arch.ARMV7 for s in CORE)


def test_token_scenario_sets_api_token_env():
    s = Scenario(name="t", db=Db.SQLITE, auth=Auth.TOKEN)
    env = s.env()
    assert env["SPOOLMAN_API_TOKEN"]  # non-empty


def test_subpath_scenario_sets_base_path():
    s = Scenario(name="t", db=Db.SQLITE, proxy=Proxy.NGINX, subpath="spoolman")
    assert s.env()["SPOOLMAN_BASE_PATH"] == "spoolman"


def test_armv7_weighs_more_than_amd64():
    light = Scenario(name="a", db=Db.SQLITE, arch=Arch.AMD64)
    heavy = Scenario(name="b", db=Db.SQLITE, arch=Arch.ARMV7)
    assert heavy.weight() > light.weight()


def test_expand_filters_and_crosses():
    out = expand(dbs=[Db.SQLITE, Db.POSTGRES], proxies=[Proxy.NGINX], arches=[Arch.AMD64])
    assert {s.db for s in out} == {Db.SQLITE, Db.POSTGRES}
    assert all(s.proxy is Proxy.NGINX for s in out)
