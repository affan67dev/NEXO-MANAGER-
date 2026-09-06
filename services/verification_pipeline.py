from services.rag.rag import build_context
from services.guardrails.guardrails import verify

def prepare(query,draft,rules=None):
    context=build_context(query)
    result=verify(draft,context,rules or [])
    return {
        "query":query,
        "context":context,
        "draft":draft,
        "approved":result["approved"],
        "problems":result["problems"]
    }
