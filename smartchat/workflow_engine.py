from copy import deepcopy

from django.urls import reverse

from .context_state import normalized_state, persist_state


VENDOR_ONBOARDING_STEPS = (
    "Sign in to or create your Arolana account",
    "Open vendor registration",
    "Complete your business profile",
    "Add contact and business information",
    "Complete the required KYC",
    "Submit your application for approval",
    "Wait for Arolana admin verification",
    "Choose a vendor subscription plan",
    "Complete your store setup",
    "Upload your products",
    "Publish approved products",
    "Manage orders and customer enquiries",
)


def _workflow(state):
    workflow = deepcopy(state.get("workflow") or {})
    if workflow.get("type") != "vendor_onboarding":
        workflow = {
            "type": "vendor_onboarding",
            "current_step": 1,
            "completed_steps": [],
            "status": "in_progress",
        }
    return workflow


def initialize_vendor_workflow(conversation):
    state = normalized_state(conversation)
    state["workflow"] = _workflow(state)
    persist_state(conversation, state)
    return state["workflow"]


def vendor_guidance(conversation, mode="guide"):
    state = normalized_state(conversation)
    workflow = _workflow(state)
    completed = set(workflow.get("completed_steps") or [])

    if mode == "kyc_complete":
        completed.add(5)
        workflow["completed_steps"] = sorted(completed)
        workflow["current_step"] = 6
    elif mode == "next":
        workflow["current_step"] = min(
            max(int(workflow.get("current_step") or 1) + 1, 1),
            len(VENDOR_ONBOARDING_STEPS),
        )

    current_step = int(workflow.get("current_step") or 1)
    if current_step >= len(VENDOR_ONBOARDING_STEPS) and current_step in completed:
        workflow["status"] = "completed"
    state["workflow"] = workflow
    state["intent"] = "vendor_onboarding_guidance"
    state["last_topic"] = "vendor_onboarding_guidance"
    persist_state(conversation, state)

    if mode == "guide":
        steps = "\n".join(
            f"{index}. {label}"
            for index, label in enumerate(VENDOR_ONBOARDING_STEPS, start=1)
        )
        message = (
            "Yes, I can guide you through it step by step. Here is the Arolana vendor journey:\n\n"
            f"{steps}\n\nLet’s start with vendor registration. I can take you through each step one at a time."
        )
    elif mode == "kyc_complete":
        message = (
            "Great, I’ve marked KYC as completed. Your next step is 6: submit your vendor "
            "application for Arolana approval. After submission, admin verification comes next."
        )
    else:
        message = (
            f"Step {current_step}: {VENDOR_ONBOARDING_STEPS[current_step - 1]}. "
            "Tell me when you complete it and I’ll continue to the next step."
        )

    actions = [{
        "type": "open_url",
        "label": "Start vendor registration",
        "url": reverse("vendor_register_redirect"),
        "primary": True,
    }]
    if current_step >= 8:
        actions.append({
            "type": "open_url",
            "label": "View vendor plans",
            "url": reverse("subscriptions:plans"),
        })
    return message, workflow, actions
