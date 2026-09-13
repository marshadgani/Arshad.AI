import { BrokerageHoldings } from '../components/finance';
import DomainPage from '../components/DomainPage';

export default function StockMarket() {
  return (
    <DomainPage slug="stocks">
      <BrokerageHoldings />
    </DomainPage>
  );
}
