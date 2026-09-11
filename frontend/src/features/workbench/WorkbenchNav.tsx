import { NavLink } from 'react-router-dom';

export function WorkbenchNav() {
  return <nav aria-label="投资工作台导航" className="flex flex-wrap gap-2">{[
    ['/investment-workbench/briefs', '每日简报'],
    ['/investment-workbench/trend-lab', '趋势策略验证'],
    ['/investment-workbench/tasks', '日常待办'],
    ['/investment-workbench', '投资卡与计划'],
    ['/investment-workbench/compare', '主题与标的比较'],
    ['/investment-workbench/journal', '成交与复盘'],
  ].map(([to, label]) => <NavLink key={to} to={to} end className={({ isActive }) => 'rounded-lg border border-border px-3 py-2 text-sm hover:border-primary ' + (isActive ? 'bg-primary/10 text-primary' : '')}>{label}</NavLink>)}</nav>;
}
