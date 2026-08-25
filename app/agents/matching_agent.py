from dotenv import load_dotenv
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient

from app.capabilities.matching_tools import (
    calculate_line_amount,
    route_to_hitl,
    run_3_way_matching,
)
from app.env import get_env


load_dotenv()


def create_matching_agent() -> Agent:
    """
    Create the primary 3-way matching orchestration agent.
    """

    base_url = get_env("FOUNDRY_OPENAI_BASE_URL")
    api_key = get_env("FOUNDRY_API_KEY")
    model = get_env("FOUNDRY_MODEL")

    if not base_url:
        raise RuntimeError(
            "foundry-openai-base-url is not configured."
        )

    if not api_key:
        raise RuntimeError(
            "foundry-api-key is not configured."
        )

    if not model:
        raise RuntimeError(
            "foundry-model is not configured."
        )

    client = OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    agent = Agent(
        client=client,
        name="three_way_matching_agent",
        instructions=(
            "You are the orchestration agent for a contract, "
            "purchase order, and invoice 3-way matching workflow. "
            "You coordinate deterministic Python tools, reason "
            "about exceptions, explain validation results, and "
            "route cases requiring human judgment to HITL. "
            "\n\n"
            "IMPORTANT: Never perform arithmetic yourself when "
            "a deterministic Python tool is available. "
            "Use the appropriate tool and rely on its result. "
            "\n\n"
            "The deterministic matching tool is the authoritative "
            "source for validation results. Never independently "
            "calculate, recalculate, override, or infer validation "
            "outcomes. When the tool returns exceptions, explain "
            "the returned exception types, fields, expected values, "
            "actual values, and tolerances using only the tool result. "
            "\n\n"
            "When the deterministic matching result has status "
            "EXCEPTION, use the route_to_hitl tool to create a "
            "pending human-review case. Do not approve, reject, "
            "or override the exception yourself. "
            "\n\n"
            "When routing to HITL, preserve the deterministic "
            "validation result exactly as returned by the matching "
            "tool. Do not modify exception values, expected values, "
            "actual values, tolerances, or evidence."
        ),
        tools=[
            calculate_line_amount,
            run_3_way_matching,
            route_to_hitl,
        ],
    )

    return agent