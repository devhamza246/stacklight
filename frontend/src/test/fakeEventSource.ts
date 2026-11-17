import { vi } from "vitest";

type Listener = (e: MessageEvent<string>) => void;

/** Minimal controllable EventSource for tests. Instances are collected in FakeEventSource.instances. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  readonly url: string;
  readyState = 0;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(type: string, data: unknown, id?: number) {
    const ev = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id ? String(id) : "" });
    this.listeners.get(type)?.forEach((fn) => fn(ev));
  }
  /** Simulate a network error; `fatal` mimics the browser giving up (readyState CLOSED). */
  fail(fatal: boolean) {
    this.readyState = fatal ? 2 : 0;
    this.onerror?.(new Event("error"));
  }
  static install() {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  }
  static get last() {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }
}
