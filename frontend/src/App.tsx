import { useCallback, useRef, useState } from "react";
import { ApprovalQueue } from "./components/ApprovalQueue";
import { ChatPanel } from "./components/ChatPanel";
import { Icon, Logo } from "./components/Icon";
import { SourceDrawer, type OpenSource } from "./components/SourceDrawer";
import { StatusPill } from "./components/StatusPill";
import { TabBar, type Tab } from "./components/TabBar";
import { ThemeToggle } from "./components/ThemeToggle";
import { TourDialog } from "./components/TourDialog";
import { TraceGraph } from "./components/TraceGraph";
import { useDemo } from "./state/useDemo";

export function App() {
  const demo = useDemo();
  const [tab, setTab] = useState<Tab>("chat");
  const [source, setSource] = useState<{ source: OpenSource; trigger: HTMLElement } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [tour, setTour] = useState<{ trigger: HTMLElement | null } | null>(null);
  const openTour = useCallback((e: { currentTarget: HTMLElement }) => setTour({ trigger: e.currentTarget }), []);

  const openSource = useCallback((s: OpenSource, trigger: HTMLElement) => setSource({ source: s, trigger }), []);
  const closeSource = useCallback(() => setSource(null), []);

  return (
    <div className="app" data-tab={tab}>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="brand">
          <Logo />
          <div className="brand-text">
            <span className="wordmark">Stacklight</span>
            <span className="tagline">AI team that answers from your docs, and keeps them current.</span>
          </div>
        </div>
        <div className="topbar-actions">
          <StatusPill info={demo.status.info} error={demo.status.error} />
          <button className="btn btn-sm tour-btn" type="button" onClick={openTour}><Icon name="help" /><span className="tour-label">How it works</span><span className="sr-only"> (take the tour)</span></button>
          <ThemeToggle />
        </div>
      </header>
      <div className="workspace">
        <ChatPanel
          run={demo.run}
          submitted={demo.submitted}
          notice={demo.notice}
          composer={demo.composer}
          composerDisabled={demo.composerDisabled}
          disabledPlaceholder={demo.disabledPlaceholder}
          preparing={demo.preparing}
          sending={demo.sending}
          onSubmit={demo.submit}
          onPick={demo.pick}
          onAudit={demo.audit}
          onRetry={demo.retry}
          onRephrase={demo.restoreQuestion}
          onTour={openTour}
          onViewTrace={() => setTab("trace")}
          onViewQueue={() => setTab("queue")}
          openChunkId={source?.source.chunkId ?? null}
          onOpenSource={openSource}
          inputRef={inputRef}
        />
        <aside className="col-side" aria-label="Trace and approval queue">
          <TraceGraph run={demo.run} />
          <ApprovalQueue approvals={demo.approvals} newIds={demo.newIds} needsHuman={demo.needsHuman} onOpenSource={openSource} onAudit={demo.audit} auditDisabled={demo.composerDisabled || demo.sending || demo.run.phase === "running"} />
        </aside>
      </div>
      <TourDialog open={tour !== null} onClose={() => setTour(null)} returnFocusTo={tour?.trigger ?? null} onTab={setTab} />
      <SourceDrawer source={source?.source ?? null} returnFocusTo={source?.trigger ?? null} onClose={closeSource} />
      <TabBar tab={tab} onChange={setTab} queueCount={demo.approvals.pending.length} />
    </div>
  );
}
