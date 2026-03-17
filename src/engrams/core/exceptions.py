# Copyright 2025 Scott McLeod (contextportal@gmail.com)
# Copyright 2025 Steve Brownlee (steve@stevebrownlee.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Custom exception types for the Context Portal MCP server."""


class ContextPortalError(Exception):
    """Base exception class for Context Portal errors."""


class DatabaseError(ContextPortalError):
    """Exception raised for database-related errors."""


class DatabaseNotInitializedError(DatabaseError):
    """Exception raised when the Engrams database does not exist yet.

    This is distinct from DatabaseError to allow callers (especially LLM agents)
    to distinguish 'database never created' from 'database exists but broken'.
    The error message includes actionable guidance.
    """

    def __init__(self, workspace_id: str, db_path: str, reason: str = ""):
        self.workspace_id = workspace_id
        self.db_path = db_path
        detail = f" ({reason})" if reason else ""
        super().__init__(
            f"Engrams database not found at '{db_path}'{detail}. "
            f"Run 'engrams init --tool <name>' in your project directory to create it, "
            f"or the database will be auto-created on the next write operation."
        )


class ConfigurationError(ContextPortalError):
    """Exception raised for configuration errors."""


class ToolArgumentError(ContextPortalError):
    """Exception raised for invalid MCP tool arguments."""


# Add more specific exceptions as needed
