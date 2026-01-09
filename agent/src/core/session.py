from livekit import rtc


class SessionState:
    def __init__(self):
        self.session_id = None
        self.room: rtc.Room | None = None  # 房间引用，用于发送 Data Channel 消息
