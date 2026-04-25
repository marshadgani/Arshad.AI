import DomainPage from '../components/DomainPage';
import { domains } from '../data/mockData';

export default function ShopifyStore() {
  return <DomainPage domain={domains.shopify} />;
}
