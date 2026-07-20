"""Function that persist an agent's tool-calling trace to the blackboard.

The tool-calling agents (Research, Parse) have tool_call messages that we post here to the blackboard, 
so that the report's worklog appendix can show what the model did and why.

The other agents only produce a structured output. They can include a justification in there.
"""

from langchain_core.messages import AIMessage


def record_tool_trace(blackboard, agent_name: str, messages) -> None:
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                blackboard.post(agent_name, "tool_call", {"tool": call["name"], "args": call["args"]})
    final = messages[-1] if messages else None
    if isinstance(final, AIMessage) and isinstance(final.content, str) and final.content.strip():
        blackboard.post(agent_name, "note", {"text": final.content.strip()[:2000]})
