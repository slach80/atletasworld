from allauth.account.adapter import DefaultAccountAdapter


class SilentAuthAdapter(DefaultAccountAdapter):
    """Suppress noisy sign-in / sign-out flash messages."""

    SUPPRESSED = {
        "account/messages/logged_in.txt",
        "account/messages/logged_out.txt",
    }

    def add_message(self, request, level, message_template, message_context=None, extra_tags=""):
        if message_template in self.SUPPRESSED:
            return
        super().add_message(request, level, message_template, message_context, extra_tags)
