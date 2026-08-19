"""Suíte embutida — as ferramentas rodam no painel, não em GitHub nem em outro domínio."""

from __future__ import annotations

from typing import Any

from osint4all.tools_suite import EMBEDDED_TOOLS


def _tool(name: str, tool_id: str, description: str, input_type: str, output: str) -> dict[str, Any]:
    return {
        "name": name,
        "type": "url",
        "url": f"/app/ferramentas?tool={tool_id}",
        "description": description,
        "status": "live",
        "pricing": "free",
        "bestFor": description,
        "input": input_type,
        "output": output,
        "opsec": "active",
        "localInstall": True,
        "googleDork": False,
        "registration": False,
        "editUrl": True,
        "api": True,
        "internal": True,
        "tool": tool_id,
        "source": "osint4all",
    }


def local_suite_branch() -> dict[str, Any]:
    children = [
        _tool(
            tool.name,
            tool.id,
            f"{tool.summary} Inspirado em {tool.inspired}.",
            tool.kind,
            "Resultado no painel OSINT4ALL",
        )
        for tool in EMBEDDED_TOOLS
    ]
    return {
        "name": "Suíte local (T)",
        "type": "folder",
        "source": "osint4all",
        "children": children,
    }
