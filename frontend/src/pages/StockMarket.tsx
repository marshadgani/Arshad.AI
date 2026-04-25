import DomainPage from '../components/DomainPage';
import { domains } from '../data/mockData';

export default function StockMarket() {
  return <DomainPage domain={domains.stocks} />;
}
