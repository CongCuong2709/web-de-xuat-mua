from . import workflow as wf
from .models import Proposal


def nav(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.must_change_password:
        return {}
    return {
        "pending_count": Proposal.objects.filter(wf.pending_q(user)).count(),
        "can_create": wf.can_create(user),
    }
