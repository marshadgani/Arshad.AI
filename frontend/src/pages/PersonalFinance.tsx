import DomainPage from '../components/DomainPage';
import { domains } from '../data/mockData';

export default function PersonalFinance() {
  return <DomainPage domain={domains.finance} />;
}
