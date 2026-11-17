# Slack Integration Guide

Owner: Solutions Engineering
Last reviewed: 2026-06-23

- Install from Settings > Integrations > Slack. The installing person must be a Slack workspace admin or have app-install permission.
- Quillbase can post to public channels. For private channels, invite the Quillbase bot with `/invite @Quillbase` first.
- Messages are limited to 40,000 characters and 50 blocks; longer content is truncated with a link to the run.
- Slack rate-limits posts to about 1 message per second per channel; Quillbase queues and retries up to 3 times.
- Slash command `/quillbase run <flow-name>` triggers a flow manually; the user must be an Editor or higher.
- Uninstalling the app pauses flows that use Slack steps; they resume when the app is reinstalled.
