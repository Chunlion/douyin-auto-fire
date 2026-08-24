DOUYIN_CHAT_URL = "https://www.douyin.com/chat"

# Ordered alternatives keep page-specific changes isolated from the workflow.
LOGIN_REQUIRED_MARKERS = (
    'text="扫码登录"',
    'text="验证码登录"',
    'text="密码登录"',
    '[class*="login"] input[placeholder*="手机号"]',
    '[class*="Login"] input[placeholder*="手机号"]',
)
RISK_MARKERS = (
    'text=安全验证',
    'text=完成验证',
    'text=验证身份',
)
SEARCH_INPUTS = (
    'input[placeholder*="搜索"]',
    'input[placeholder="搜索"]',  # 精确匹配备用 selector，兼容慢渲染时属性值变化
    '[role="textbox"][placeholder*="搜索"]',
    'input[aria-label*="搜索"]',
    '[role="textbox"][aria-label*="搜索"]',
)
LOGIN_MARKERS = SEARCH_INPUTS
CHAT_HEADER_TITLES = (
    '.RightPanelHeadertitle',
    '[class*="RightPanelHeader"] [class*="title"]',
    '[class*="chatHeader"] [class*="title"]',
    '[class*="ChatHeader"] [class*="title"]',
)
CURRENT_CONVERSATIONS = (
    '[data-e2e="conversation-item"][class*="curConversation"]',
    '[data-e2e="conversation-item"][aria-selected="true"]',
    '[class*="conversationConversationItemcurConversation"]',
)
MESSAGE_INPUTS = (
    '[data-contents="true"]',
    '.DraftEditor-editor [contenteditable="true"]',
    '.DraftEditor-root [contenteditable="true"]',
    '[contenteditable="true"][data-placeholder*="发送消息"]',
    '[contenteditable="true"][aria-label*="消息"]',
    '[contenteditable="true"]',
    'textarea[placeholder*="消息"]',
)
IMAGE_INPUTS = ('input[type="file"][accept*="image"]', 'input[type="file"]')
STICKER_BUTTONS = (
    'svg.messageMsgInputiconAction',
    'button[aria-label*="表情"]',
    '[role="button"][aria-label*="表情"]',
    '[title*="表情"]',
)
STICKER_PANELS = (
    '.componentsemojiemojiPanel',
    '[class*="emojiPanel"]',
    '[role="dialog"]',
    '[class*="sticker"]',
)
