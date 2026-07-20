from typing import Annotated, TypedDict

from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.config.settings import settings


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def call_model(state: AgentState) -> AgentState:
    model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
    )

    response = model.invoke(state["messages"])

    return {"messages": [response]}


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("agent", call_model)

    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)

    return graph.compile()
