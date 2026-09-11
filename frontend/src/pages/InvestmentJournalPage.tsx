import { WorkbenchNav } from '@/features/workbench/WorkbenchNav';
import { TradeJournal } from '@/features/workbench/TradeJournal';

export function InvestmentJournalPage() {
  return <div className="mx-auto max-w-[1440px] space-y-6 p-5 lg:p-8">
    <header className="border-b border-border pb-5"><p className="text-xs tracking-[.2em] text-primary">BRUCE / INVESTMENT JOURNAL</p><h1 className="mt-2 text-2xl font-semibold">投资工作台</h1></header>
    <WorkbenchNav />
    <TradeJournal />
  </div>;
}
