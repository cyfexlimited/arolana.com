from rest_framework import serializers

from .models import (
    AIConversation,
    AICustomerMemory,
    AIFeedback,
    AIKnowledgeBase,
    AILearnedKnowledge,
    AIMessage,
    AISettings,
    AITrainingData,
    HumanTakeoverRequest,
)


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = [
            "id", "conversation", "sender_type", "message", "image", "source_type",
            "source_label", "confidence", "is_read_by_customer", "created_at",
        ]
        read_only_fields = fields


class AIConversationSerializer(serializers.ModelSerializer):
    messages = AIMessageSerializer(many=True, read_only=True)

    class Meta:
        model = AIConversation
        fields = [
            "id", "title", "status", "audience", "channel", "assigned_admin",
            "last_message_at", "created_at", "messages",
        ]
        read_only_fields = fields


class AIKnowledgeBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIKnowledgeBase
        fields = "__all__"


class AILearnedKnowledgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AILearnedKnowledge
        fields = "__all__"


class AICustomerMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AICustomerMemory
        fields = "__all__"
        read_only_fields = ["user", "session_key", "device_id"]


class AIFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIFeedback
        fields = "__all__"


class AITrainingDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = AITrainingData
        fields = "__all__"


class AISettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AISettings
        exclude = []


class HumanTakeoverRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = HumanTakeoverRequest
        fields = "__all__"
