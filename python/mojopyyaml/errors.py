class YAMLError(Exception):
    pass


class MarkedYAMLError(YAMLError):
    pass


class ParserError(MarkedYAMLError):
    pass


class ScannerError(MarkedYAMLError):
    pass


class ConstructorError(MarkedYAMLError):
    pass


class ComposerError(MarkedYAMLError):
    pass


class EmitterError(YAMLError):
    pass


class SerializerError(YAMLError):
    pass


class RepresenterError(YAMLError):
    pass
