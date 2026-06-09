/**
 * ai-elements component suite — adapted for homelabhealth's design tokens and data model.
 *
 * Install source: https://elements.ai-sdk.dev/api/registry/all.json
 * Docs: https://elements.ai-sdk.dev/docs
 *
 * All components use the project's CSS custom properties from globals.css
 * via Tailwind utility classes. Import any component individually from
 * `@/components/ai-elements/<name>` or the full set from this barrel.
 */

// ——— Chat layout ———
export {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
  ConversationDownload,
} from './conversation'

// ——— Message display ———
export {
  Message,
  MessageContent,
  MessageActions,
  MessageAction,
  MessageBranch,
  MessageBranchContent,
  MessageBranchSelector,
  MessageBranchPrevious,
  MessageBranchNext,
  MessageBranchPage,
  MessageResponse,
  MessageToolbar,
} from './message'

// ——— Code syntax highlighting (Shiki, multi-theme, line numbers) ———
export {
  CodeBlock,
  CodeBlockContainer,
  CodeBlockHeader,
  CodeBlockTitle,
  CodeBlockFilename,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockLanguageSelector,
  CodeBlockLanguageSelectorTrigger,
  CodeBlockLanguageSelectorValue,
  CodeBlockLanguageSelectorContent,
  CodeBlockLanguageSelectorItem,
} from './code-block'

// ——— Prompt input (slash commands, file attachments, model selector) ———
export {
  PromptInput,
  PromptInputProvider,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputHeader,
  PromptInputFooter,
  PromptInputTools,
  PromptInputButton,
  PromptInputActionMenu,
  PromptInputActionMenuTrigger,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputSubmit,
  PromptInputSelect,
  PromptInputSelectTrigger,
  PromptInputSelectContent,
  PromptInputSelectItem,
  PromptInputSelectValue,
  PromptInputHoverCard,
  PromptInputHoverCardTrigger,
  PromptInputHoverCardContent,
} from './prompt-input'

// ——— Tool call display ———
export {
  Tool,
  ToolHeader,
  ToolContent,
  ToolInput,
  ToolOutput,
  getStatusBadge,
} from './tool'

// ——— Reasoning / thinking blocks ———
export {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
  useReasoning,
} from './reasoning'

// ——— Attachments ———
export {
  Attachments,
  Attachment,
  AttachmentImage,
  AttachmentFile,
  AttachmentDelete,
} from './attachments'

// ——— Sources (ai-elements style) ———
export {
  Sources,
  SourcesTrigger,
  SourcesContent,
  Source,
} from './sources'

// ——— Inline citation ———
export { InlineCitation } from './inline-citation'

// ——— UI primitives ———
export { Shimmer } from './shimmer'
export { Suggestion } from './suggestion'
export { Snippet } from './snippet'
