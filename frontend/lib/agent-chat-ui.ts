/**
 * Master switch for the agent chat surfaces.
 *
 * `false` hides the global widget and every Ask / Review control, and the
 * widget context refuses to open or send. Set this to `true` to restore
 * the chat UI. The widget, context, and `sendAgentChat` client stay in
 * the tree either way.
 */
export const AGENT_CHAT_UI_ENABLED: boolean = false;
