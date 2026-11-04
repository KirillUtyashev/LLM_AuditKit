"""Domain errors for template population; messages omit resume/value contents."""


class TemplatePopulationError(Exception):
    """Base class for template population failures."""


class TemplatePopulationConfigurationError(TemplatePopulationError):
    """Column mappings or other population configuration are invalid."""


class TemplatePopulationDatasetError(TemplatePopulationError):
    """Input tables violate the population schema or matching contract."""


class TemplatePopulationPlaceholderError(TemplatePopulationDatasetError):
    """A source placeholder is malformed or lacks a valid mapped value."""
