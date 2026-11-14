<?php

namespace App\PromoStandards;

use App\Models\Supplier;

/**
 * The ten PromoStandards services the hub knows about.
 *
 * VERIFY BEFORE PRODUCTION: versions, namespaces, method names and probe parameters below
 * were written from memory of the specs, without access to promostandards.org or any WSDL
 * (the build sandbox could not reach it). Check each against the published WSDL for the
 * versions your suppliers actually run. Everything that depends on them lives in this file
 * and config/promostandards.php so a correction is a one-file change.
 */
enum Service: string
{
    case ProductData = 'product_data';
    case MediaContent = 'media_content';
    case ProductPricing = 'product_pricing';
    case Inventory = 'inventory';
    case PurchaseOrder = 'purchase_order';
    case OrderStatus = 'order_status';
    case OrderShipment = 'order_shipment';
    case Invoice = 'invoice';
    case CompanyData = 'company_data';
    case RemittanceAdvice = 'remittance_advice';

    public function label(): string
    {
        return match ($this) {
            self::ProductData => 'Product Data',
            self::MediaContent => 'Media Content',
            self::ProductPricing => 'Product Pricing and Configuration',
            self::Inventory => 'Inventory',
            self::PurchaseOrder => 'Purchase Order',
            self::OrderStatus => 'Order Status',
            self::OrderShipment => 'Order Shipment Notification',
            self::Invoice => 'Invoice',
            self::CompanyData => 'Company Data',
            self::RemittanceAdvice => 'Remittance Advice',
        };
    }

    public function defaultVersion(): string
    {
        return match ($this) {
            self::ProductData, self::Inventory, self::OrderStatus, self::OrderShipment => '2.0.0',
            self::MediaContent => '1.1.0',
            default => '1.0.0',
        };
    }

    /** Path segment used in the SOAP namespace, e.g. ProductDataService. */
    public function namespaceSegment(): string
    {
        return match ($this) {
            self::ProductData => 'ProductDataService',
            self::MediaContent => 'MediaContentService',
            self::ProductPricing => 'PricingAndConfigurationService',
            self::Inventory => 'InventoryService',
            self::PurchaseOrder => 'PurchaseOrderService',
            self::OrderStatus => 'OrderStatusService',
            self::OrderShipment => 'OrderShipmentNotificationService',
            self::Invoice => 'InvoiceService',
            self::CompanyData => 'CompanyDataService',
            self::RemittanceAdvice => 'RemittanceAdviceService',
        };
    }

    public function namespace(string $version): string
    {
        return "http://www.promostandards.org/WSDL/{$this->namespaceSegment()}/{$version}/";
    }

    /**
     * Read-only call used to prove credentials and endpoint work, or null when no safe probe
     * exists. Purchase Order, Order Status, Shipment, Invoice, Company Data and Remittance are
     * never probed: the hub must not send a PO to test a connection, and the others need
     * real order or invoice numbers.
     *
     * @return array{method: string, needs_sample: bool, params: array<string, string>}|null
     */
    public function probe(Supplier $supplier): ?array
    {
        $sample = (string) $supplier->sample_product_id;

        return match ($this) {
            self::ProductData => [
                'method' => 'getProductSellable',
                'needs_sample' => false,
                'params' => ['localizationCountry' => 'US', 'localizationLanguage' => 'en', 'isSellable' => 'true'],
            ],
            self::Inventory => [
                'method' => 'getInventoryLevels',
                'needs_sample' => true,
                'params' => ['productId' => $sample],
            ],
            self::ProductPricing => [
                'method' => 'getAvailableLocations',
                'needs_sample' => true,
                'params' => ['productId' => $sample, 'localizationCountry' => 'US', 'localizationLanguage' => 'en'],
            ],
            self::MediaContent => [
                'method' => 'getMediaDateModified',
                'needs_sample' => false,
                'params' => ['changeTimeStamp' => now()->subDay()->utc()->format('Y-m-d\TH:i:s')],
            ],
            default => null,
        };
    }

    /** Tolerant lookup from the names the PromoStandards directory might use. */
    public static function fromDirectoryName(string $name): ?self
    {
        $key = preg_replace('/[^a-z]/', '', strtolower($name));
        $key = preg_replace('/(service|webservice)$/', '', $key);

        return match ($key) {
            'productdata', 'product' => self::ProductData,
            'media', 'mediacontent' => self::MediaContent,
            'ppc', 'pricingandconfiguration', 'productpricingandconfiguration', 'pricing' => self::ProductPricing,
            'inventory' => self::Inventory,
            'purchaseorder', 'po' => self::PurchaseOrder,
            'orderstatus' => self::OrderStatus,
            'ordershipmentnotification', 'ordershipment', 'osn', 'shipment' => self::OrderShipment,
            'invoice' => self::Invoice,
            'companydata', 'company' => self::CompanyData,
            'remittanceadvice', 'remittance' => self::RemittanceAdvice,
            default => null,
        };
    }
}
