"""Rule loading at startup (fail-closed) plus version/hash of what was loaded.

Three design decisions, each with a verified reason:

  1. The YAML files are read **once**, at boot. Changing a rule requires a service
     restart. There is no hot reload: a correction already published into a client
     channel is not the place to discover mid-request that a YAML broke. The hash
     of what was loaded is exposed on GET /meta/config so "which rules are active
     right now" can be answered without touching disk.

  2. A malformed YAML **aborts startup**, same as `config.py`. A deployment that
     does not come up beats a service classifying with partial rules.

  3. `none` must exist in `prompts.yaml`, and every evaluated agent must carry a
     prefix for the channel it received traffic on. If missing, the message is
     ignored: publishing without an identifiable label would confuse the customer
     more than the original text did.

IDs in `agents.yaml` are `ai_assistants.id` -- the value arriving in
`payload.meta.ai_assistant_id`, injected by postReply() in
libredesk/internal/aiagent/worker.go -- NOT the user_id.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("hub-api.rules")

# Name of the option meaning "do not intervene". Mandatory.
NONE_OPTION = "none"

# Valid channels under `prefixes`. `chat` covers LiveChat and WhatsApp (same
# treatment); `email` gets the more formal tone. Matches LibreDesk inbox.channel.
VALID_CHANNELS = ("chat", "email")


class RulesError(RuntimeError):
    """Unreadable or incomplete rule: the service must not start."""


@dataclass(frozen=True)
class AgentRule:
    assistant_id: int
    name: str
    enabled: bool
    prefixes: dict[str, str] = field(default_factory=dict)
    # users.id del bot para re-asignar (post_action revive-assistant); None = omitir.
    assign_user_id: int | None = None

    def prefix_for(self, channel: str | None) -> str | None:
        """Prefix for the channel, or None when undeclared (fail-closed)."""
        if not channel:
            return None
        return self.prefixes.get(channel)


@dataclass(frozen=True)
class Rules:
    """Validated rules, immutable after startup."""

    question_instructions: str
    options: dict[str, str]
    agents: dict[int, AgentRule]
    rules_hash: str
    rules_version: str
    # Efectos secundarios declarados por opciones (post_action del YAML), vacio
    # en la mayoria. Default aqui porque dataclass exige defaults al final.
    post_actions: dict[str, str] = field(default_factory=dict)

    def agent(self, assistant_id: int) -> AgentRule | None:
        return self.agents.get(assistant_id)

    def is_evaluable(self, assistant_id: int) -> bool:
        """G3: only declared AND enabled agents. Absent = do not evaluate."""
        rule = self.agents.get(assistant_id)
        return bool(rule and rule.enabled)

    def action_text(self, choice: str | None) -> str | None:
        """Action block for the JEV choice. `none`/unknown = None."""
        if not choice or choice == NONE_OPTION:
            return None
        return self.options.get(choice)

    def post_action(self, choice: str | None) -> str | None:
        """Side effect declared by an option (e.g. revive-assistant), or None.

        Only applied AFTER a successful publish: reassigning the bot without a
        published correction would reset its turn counter for nothing.
        """
        if not choice or choice == NONE_OPTION:
            return None
        return self.post_actions.get(choice)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise RulesError(f"{path.name} not found at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # noqa: PERF203 - a failure here aborts startup
        raise RulesError(f"{path.name}: invalid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise RulesError(f"{path.name}: expected a mapping at the top level")
    return data


def _load_prompts(path: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    data = _read_yaml(path)

    question = data.get("question")
    if not isinstance(question, dict):
        raise RulesError(f"{path.name}: missing 'question' mapping")
    instructions = question.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise RulesError(f"{path.name}: 'question.instructions' must be a non-empty string")

    options = data.get("options")
    if not isinstance(options, dict) or not options:
        raise RulesError(f"{path.name}: 'options' must be a non-empty mapping")

    clean: dict[str, str] = {}
    post_actions: dict[str, str] = {}
    known_post_actions = {"revive-assistant"}
    for key, desc in options.items():
        if not isinstance(key, str) or not key.strip():
            raise RulesError(f"{path.name}: option keys must be non-empty strings")
        # Dos formas admitidas:
        #   clave: "texto plano"                     (legacy, sigue siendo lo comun)
        #   clave: {text: "...", post_action: "..."} (cuando la accion ademas actua)
        if isinstance(desc, dict):
            raw_text = desc.get("text")
            pa = desc.get("post_action")
            if pa is not None:
                pa = str(pa).strip()
                if pa not in known_post_actions:
                    raise RulesError(
                        f"{path.name}: option {key!r} declares unknown post_action "
                        f"{pa!r} (valid: {sorted(known_post_actions)})"
                    )
                post_actions[key.strip()] = pa
        else:
            raw_text = desc
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise RulesError(f"{path.name}: option {key!r} needs a non-empty description")
        clean[key.strip()] = " ".join(raw_text.split())

    # Without `none` there is no way to say "do not publish": publishing would
    # silently become the default, the opposite of what this feature must do.
    if NONE_OPTION not in clean:
        raise RulesError(
            f"{path.name}: option {NONE_OPTION!r} is mandatory (fail-closed default)"
        )
    return instructions.strip(), clean, post_actions


def _load_agents(path: Path) -> dict[int, AgentRule]:
    data = _read_yaml(path)
    raw = data.get("agents")
    if not isinstance(raw, dict):
        raise RulesError(f"{path.name}: missing 'agents' mapping")

    agents: dict[int, AgentRule] = {}
    for key, value in raw.items():
        try:
            assistant_id = int(key)
        except (TypeError, ValueError) as exc:
            raise RulesError(
                f"{path.name}: agent id {key!r} is not an integer (use ai_assistants.id)"
            ) from exc
        if assistant_id <= 0:
            raise RulesError(f"{path.name}: agent id must be positive, got {assistant_id}")
        if not isinstance(value, dict):
            raise RulesError(f"{path.name}: agent {assistant_id} must be a mapping")

        enabled = bool(value.get("enabled", False))
        name = str(value.get("name") or f"assistant-{assistant_id}")

        raw_assign = value.get("assign_user_id")
        assign_user_id: int | None = None
        if raw_assign is not None:
            try:
                assign_user_id = int(raw_assign)
            except (TypeError, ValueError):
                raise RulesError(
                    f"{path.name}: agent {assistant_id} 'assign_user_id' is not an integer"
                )
            if assign_user_id <= 0:
                raise RulesError(
                    f"{path.name}: agent {assistant_id} 'assign_user_id' must be positive"
                )

        prefixes_raw = value.get("prefixes") or {}
        if not isinstance(prefixes_raw, dict):
            raise RulesError(f"{path.name}: agent {assistant_id} 'prefixes' must be a mapping")
        prefixes: dict[str, str] = {}
        for ch, text in prefixes_raw.items():
            if ch not in VALID_CHANNELS:
                raise RulesError(
                    f"{path.name}: agent {assistant_id} has unknown channel {ch!r} "
                    f"(valid: {', '.join(VALID_CHANNELS)})"
                )
            if not isinstance(text, str) or not text.strip():
                raise RulesError(f"{path.name}: agent {assistant_id} prefix {ch!r} is empty")
            prefixes[ch] = text.strip()

        # An enabled agent without a prefix cannot be published with a label.
        if enabled and not prefixes:
            raise RulesError(
                f"{path.name}: agent {assistant_id} is enabled but declares no prefixes"
            )

        agents[assistant_id] = AgentRule(
            assistant_id=assistant_id, name=name, enabled=enabled, prefixes=prefixes,
            assign_user_id=assign_user_id,
        )
    return agents


def load_rules(rules_dir: Path | str = "rules") -> Rules:
    """Read and validate every YAML. Raises RulesError if anything is incomplete."""
    base = Path(rules_dir)
    prompts_path = base / "prompts.yaml"
    agents_path = base / "agents.yaml"
    augmenter_path = base / "prompt-augmenter.md"

    instructions, options, post_actions = _load_prompts(prompts_path)
    agents = _load_agents(agents_path)

    if not augmenter_path.exists():
        raise RulesError(f"prompt-augmenter.md not found at {augmenter_path}")

    # Hash over the raw content of all three sources: it changes whenever any
    # rule changes, including the augmenter wording.
    digest = hashlib.sha256()
    for p in (prompts_path, agents_path, augmenter_path):
        digest.update(p.name.encode())
        digest.update(b"\0")
        digest.update(p.read_bytes())
        digest.update(b"\0")
    full = digest.hexdigest()

    rules = Rules(
        question_instructions=instructions,
        post_actions=post_actions,
        options=options,
        agents=agents,
        rules_hash=full[:12],
        rules_version=full[:8],
    )
    log.info(
        "rules loaded | hash=%s | actions=%s | agents=%s",
        rules.rules_hash,
        sorted(options),
        {a: (r.name, r.enabled) for a, r in sorted(agents.items())},
    )
    return rules
