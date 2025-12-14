"""
advisor agent interface.

agents will:

- receive tick + event streams
- hold internal state
- output intentions or actions
- never directly execute trades (policy layer separate)

todo:
- define async vs sync interface
- define reward shaping for sim mode
"""


class AgentInterface:
    def on_tick(self, tick):
        pass

    def on_event(self, event):
        pass

    def decide(self):
        return None

