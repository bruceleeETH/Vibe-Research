import { Link } from 'react-router-dom';

export function InvestmentCardLink({ code, name = '' }: { code: string; name?: string }) {
  return <Link className="mr-3 whitespace-nowrap text-xs text-primary hover:underline" to={'/investment-workbench?' + new URLSearchParams({ code, name })}>投资卡</Link>;
}
