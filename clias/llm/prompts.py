"""Prompt templates used across the pipeline."""

SHELL_CLASSIFY = """\
You are a software analyst. Given the following shell command and its output,
classify it into a high-level operation category and describe what it does.

Command: {command}
Working directory: {cwd}
Exit code: {exit_code}
Stdout (truncated):
{stdout}
Stderr (truncated):
{stderr}

Respond in JSON:
{{
  "tool": "<name of the CLI tool being invoked, e.g. git, docker, npm>",
  "operation": "<short verb-noun label, e.g. build-project, run-tests>",
  "description": "<one sentence explaining what this command does>",
  "flags_used": ["<list of flags/options used>"],
  "is_destructive": <true|false>
}}
"""

SHELL_CLASSIFY_API = """\
You are a software analyst. Given the following API call (curl/httpie) and its
pre-parsed data, classify it into a high-level operation.

Command: {command}
Working directory: {cwd}
Exit code: {exit_code}
HTTP method: {http_method}
URL: {url}
Request body: {request_body}
Stdout (truncated):
{stdout}
Stderr (truncated):
{stderr}

Respond in JSON:
{{
  "tool": "<name of the API service, e.g. github, stripe, slack>",
  "operation": "<short verb-noun label, e.g. list-issues, create-charge>",
  "description": "<one sentence explaining what this API call does>",
  "flags_used": ["<list of flags/options used in the command>"],
  "is_destructive": <true|false>,
  "api_resource": "<the REST resource being acted on, e.g. issues, charges, messages>"
}}
"""

VISION_DESCRIBE = """\
Describe the application UI shown in these screenshots. For each screenshot:
1. Identify the application name and window title.
2. Describe what the user appears to be doing.
3. List any buttons, menus, or inputs that are visible and relevant.

Respond in JSON as a list:
[
  {{
    "frame_index": <int>,
    "application": "<app name>",
    "window_title": "<title>",
    "user_action": "<what the user is doing>",
    "ui_elements": ["<visible buttons/menus/inputs>"]
  }}
]
"""

SPEC_FILL = """\
You are documenting a CLI tool. Given the observed command patterns below,
produce a complete ToolSpec in JSON format.

Observed patterns:
{patterns}

The spec must follow this structure:
{{
  "name": "<tool name>",
  "description": "<what the tool does>",
  "version": "observed",
  "capabilities": [
    {{"name": "...", "description": "...", "related_commands": ["..."]}}
  ],
  "commands": [
    {{
      "canonical": "<full command, e.g. git commit>",
      "description": "...",
      "arguments": [{{"name": "...", "description": "...", "required": true|false}}],
      "flags": [{{"flag": "...", "description": "...", "takes_value": true|false}}],
      "examples": ["..."],
      "gui_equivalent": null
    }}
  ],
  "workflows": [
    {{
      "name": "...",
      "description": "...",
      "steps": [{{"description": "...", "command_ref": "...", "typical_args": {{}}}}]
    }}
  ],
  "examples": [
    {{"description": "...", "command": "..."}}
  ]
}}

Fill in descriptions and documentation even for things not directly observed.
Use your knowledge of the tool to provide accurate, helpful descriptions.
"""

NL_TRANSLATE = """\
You are a CLI assistant for **{tool_name}**.

{tool_description}

Available commands:
{commands_summary}

The user wants: "{user_input}"

Return ONLY the exact shell command(s) to accomplish this. If multiple commands
are needed, put each on its own line. Do not include explanations — just the
commands.
"""

MERGE_VISION_SHELL = """\
You are correlating UI observations with shell commands to understand a
software tool's behavior.

UI observations (timestamped):
{ui_actions}

Shell commands (timestamped):
{shell_events}

For each shell command, determine if there is a corresponding UI action that
triggered it or relates to it. Return JSON:
[
  {{
    "command": "<the shell command>",
    "gui_equivalent": "<description of the UI action, or null>",
    "correlation_confidence": <0.0 to 1.0>
  }}
]
"""
