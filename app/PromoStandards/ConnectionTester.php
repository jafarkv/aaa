<?php

namespace App\PromoStandards;

use App\Models\Supplier;
use App\Models\SupplierEndpoint;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use RuntimeException;

/**
 * Runs one safe, read-only probe per enabled service and records the outcome on the endpoint.
 * Product Data is always tested first because its first productId is reused to probe
 * Inventory, Pricing and Media, which need a real product.
 */
class ConnectionTester
{
    public function __construct(private readonly RawPayloadStore $rawStore) {}

    /** @return array<string, array{status: string, message: string}> keyed by service value */
    public function test(Supplier $supplier): array
    {
        $credentials = $supplier->credentials;
        if (! $credentials) {
            throw new RuntimeException("Supplier {$supplier->slug} has no credentials saved.");
        }

        $endpoints = $supplier->endpoints()->where('is_enabled', true)->get()
            // Product Data first so the sample product id exists before the rest run.
            ->sortBy(fn (SupplierEndpoint $e) => $e->service === Service::ProductData->value ? 0 : 1);

        $results = [];
        foreach ($endpoints as $endpoint) {
            $results[$endpoint->service] = $this->probe($supplier, $endpoint, $credentials->username, $credentials->password);
            $supplier->refresh();
        }

        return $results;
    }

    /** @return array{status: string, message: string} */
    private function probe(Supplier $supplier, SupplierEndpoint $endpoint, string $username, string $password): array
    {
        $service = $endpoint->serviceEnum();
        $probe = $service?->probe($supplier);

        if ($service === null || $probe === null) {
            return $this->record($endpoint, 'skipped', 'No safe read-only probe for this service; it is verified on first real use.');
        }
        if ($probe['needs_sample'] && ! $supplier->sample_product_id) {
            return $this->record($endpoint, 'skipped', 'Needs a sample product id; test Product Data first.');
        }

        $xml = SoapEnvelope::build($service, $endpoint->version, $probe['method'], $username, $password, $probe['params']);

        try {
            $response = Http::timeout(config('promostandards.timeout'))
                ->withHeaders(['SOAPAction' => $probe['method']])
                ->withBody($xml, 'text/xml; charset=utf-8')
                ->post($endpoint->url);
        } catch (ConnectionException $e) {
            return $this->record($endpoint, 'failed', $this->scrub('Could not reach supplier: '.$e->getMessage(), $username, $password));
        }

        $body = $response->body();
        $this->rawStore->store(
            $supplier, $service, $probe['method'],
            SoapEnvelope::requestHash($service, $endpoint->version, $probe['method'], $probe['params']),
            $body, $response->status(),
        );

        $result = SoapResult::parse($body);

        // SOAP faults arrive as HTTP 500, so parse the body before judging the status code.
        if ($result->ok && $response->successful()) {
            if ($service === Service::ProductData && $result->productIds !== []) {
                $supplier->update(['sample_product_id' => $result->productIds[0]]);
            }

            return $this->record($endpoint, 'passed', "{$probe['method']} returned a valid response.");
        }

        $reason = $result->errors !== [] ? implode('; ', $result->errors) : "HTTP {$response->status()}";

        return $this->record($endpoint, 'failed', $this->scrub($reason, $username, $password));
    }

    /** @return array{status: string, message: string} */
    private function record(SupplierEndpoint $endpoint, string $status, string $message): array
    {
        $endpoint->update([
            'last_tested_at' => now(),
            'last_test_status' => $status,
            'last_test_message' => $message,
        ]);

        return ['status' => $status, 'message' => $message];
    }

    /** Suppliers sometimes echo the login in an error. Never let it reach our database or screen. */
    private function scrub(string $message, string $username, string $password): string
    {
        foreach (array_filter([$password, $username]) as $secret) {
            $message = str_replace($secret, '[redacted]', $message);
        }

        return $message;
    }
}
