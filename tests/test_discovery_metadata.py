"""Public discovery facts must match the shipped package and tool contract."""
from pathlib import Path
import json
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_machine_facts_match_package_and_tools():
    facts=json.loads((ROOT/'docs/project-facts.json').read_text(encoding='utf-8'))
    served=json.loads((ROOT/'site/project-facts.json').read_text(encoding='utf-8'))
    package=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']
    tools=json.loads((ROOT/'docs/tools.json').read_text(encoding='utf-8'))['tools']
    assert facts==served
    assert facts['artifact_type']=='project_facts'
    assert facts['package_name']==package['name']
    assert facts['version']==package['version']
    assert facts['tool_count']==len(tools)==22
    assert facts['transport']=='stdio'
    assert facts['evidence']['tool_schemas'].endswith('/docs/tools.json')
    assert any('not release-tested' in item for item in facts['limitations'])


def test_registry_manifest_describes_actual_custom_installation():
    registry=json.loads((ROOT/'server.json').read_text(encoding='utf-8'))
    package=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']
    assert registry['name']=='io.github.votsie/instagram-obscura-mcp'
    assert registry['version']==package['version']
    assert registry['repository']['url']==package['urls']['Repository']
    assert len(registry['description'])<=100
    assert registry['websiteUrl']=='https://votsie.github.io/instagram-obscura-mcp/installation/'
    # No hosted endpoint or registry package is advertised before one exists.
    assert 'packages' not in registry and 'remotes' not in registry
