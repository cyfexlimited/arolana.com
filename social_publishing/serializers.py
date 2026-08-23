from rest_framework import serializers


class InstagramVideoPublicationSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=("vendor", "provider", "admin"),
        required=False,
    )
    content_type = serializers.ChoiceField(
        choices=(
            "products.product",
            "products.productvideo",
            "installers.serviceportfolio",
            "installers.serviceprojectmedia",
        )
    )
    object_id = serializers.IntegerField(min_value=1)
    # A fresh request requires bytes. A genuine post-approval retry may reuse
    # the still-active deferred lease after ownership is checked by the view.
    video = serializers.FileField(allow_empty_file=False, required=False)
    caption = serializers.CharField(required=False, allow_blank=True, max_length=2200, default="")
    share_to_feed = serializers.BooleanField(required=False, default=True)
    retry = serializers.BooleanField(required=False, default=False, write_only=True)

    def validate(self, attrs):
        if attrs.get("video") is None and not attrs.get("retry"):
            raise serializers.ValidationError({"video": "A video upload is required."})
        return attrs

    def validate_video(self, video):
        content_type = str(getattr(video, "content_type", "") or "").lower()
        if not content_type.startswith("video/"):
            raise serializers.ValidationError("Upload a valid video file.")
        return video
