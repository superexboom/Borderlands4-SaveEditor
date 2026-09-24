"""Shared safe YAML codec, including the game's unknown scalar/container tags."""

import yaml

try:
    from yaml import CSafeLoader as SafeLoader, CSafeDumper as SafeDumper
except ImportError:
    from yaml import SafeLoader, SafeDumper


class GameLoader(SafeLoader):
    pass


def _ignore_tag(loader, _tag, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


GameLoader.add_multi_constructor("", _ignore_tag)


def get_yaml_loader():
    return GameLoader


def dump_yaml(value, **kwargs):
    return yaml.dump(value, Dumper=SafeDumper, **kwargs)
