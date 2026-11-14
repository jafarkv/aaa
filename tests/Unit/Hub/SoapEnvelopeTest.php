<?php

namespace Tests\Unit\Hub;

use App\PromoStandards\Service;
use App\PromoStandards\SoapEnvelope;
use App\PromoStandards\SoapResult;
use PHPUnit\Framework\TestCase;

class SoapEnvelopeTest extends TestCase
{
    public function test_envelope_is_well_formed_xml_even_with_hostile_credentials(): void
    {
        $xml = SoapEnvelope::build(Service::ProductData, '2.0.0', 'getProductSellable', 'us<er>&"', "pa'ss</shar:password>", ['isSellable' => 'true']);

        $doc = new \DOMDocument;
        $this->assertTrue($doc->loadXML($xml), 'credentials must be XML-escaped');
        $this->assertStringContainsString('GetProductSellableRequest', $xml);
        $this->assertStringContainsString('http://www.promostandards.org/WSDL/ProductDataService/2.0.0/', $xml);
    }

    public function test_request_hash_excludes_credentials_and_ignores_param_order(): void
    {
        $a = SoapEnvelope::requestHash(Service::Inventory, '2.0.0', 'getInventoryLevels', ['b' => '2', 'a' => '1']);
        $b = SoapEnvelope::requestHash(Service::Inventory, '2.0.0', 'getInventoryLevels', ['a' => '1', 'b' => '2']);

        $this->assertSame($a, $b);
    }

    public function test_soap_fault_is_reported_as_failure(): void
    {
        $result = SoapResult::parse('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault><faultstring>Bad login</faultstring></s:Fault></s:Body></s:Envelope>');

        $this->assertFalse($result->ok);
        $this->assertSame(['SOAP fault: Bad login'], $result->errors);
    }

    public function test_service_message_error_is_failure_even_without_a_fault(): void
    {
        $result = SoapResult::parse('<Envelope><Body><R><ServiceMessageArray><ServiceMessage><code>105</code><description>Auth failed</description><severity>Error</severity></ServiceMessage></ServiceMessageArray></R></Body></Envelope>');

        $this->assertFalse($result->ok);
        $this->assertStringContainsString('Auth failed', $result->errors[0]);
    }

    public function test_product_ids_are_extracted_and_deduplicated(): void
    {
        $result = SoapResult::parse('<Envelope><Body><R><ProductSellableArray><ProductSellable><productId>A1</productId></ProductSellable><ProductSellable><productId>A1</productId></ProductSellable><ProductSellable><productId>B2</productId></ProductSellable></ProductSellableArray></R></Body></Envelope>');

        $this->assertTrue($result->ok);
        $this->assertSame(['A1', 'B2'], $result->productIds);
    }

    public function test_garbage_is_a_failure_not_an_exception(): void
    {
        $this->assertFalse(SoapResult::parse('not xml at all')->ok);
        $this->assertFalse(SoapResult::parse('')->ok);
        $this->assertFalse(SoapResult::parse(null)->ok);
    }
}
