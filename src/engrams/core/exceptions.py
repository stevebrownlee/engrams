"""Custom exception types for the Context Portal MCP server."""

class ContextPortalError(Exception):
    """Base exception class for Context Portal errors."""

class DatabaseError(ContextPortalError):
    """Exception raised for database-related errors."""

class ConfigurationError(ContextPortalError):
    """Exception raised for configuration errors."""

class ToolArgumentError(ContextPortalError):
    """Exception raised for invalid MCP tool arguments."""

# Add more specific exceptions as needed