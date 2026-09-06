class TwilioAdapter:
    """
    Telephony adapter placeholder.
    Configure official Twilio credentials later through environment variables.
    Never hard-code credentials.
    """
    def inbound(self,payload):
        return {"source":"twilio","payload":payload}
