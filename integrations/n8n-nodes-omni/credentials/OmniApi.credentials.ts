import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class OmniApi implements ICredentialType {
	name = 'omniApi';

	displayName = 'Omni API';

	documentationUrl = 'https://docs.n8n.io/integrations/community-nodes/';

	properties: INodeProperties[] = [
		{
			displayName: 'API Base URL',
			name: 'apiBaseUrl',
			type: 'string',
			default: 'https://13-140-169-62.sslip.io/api',
			description:
				'Base URL of your Omni control plane API (the operator sets the real production hostname).',
		},
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description: 'An omni_sk_ API key minted in Omni under Settings → Developer.',
		},
	];

	// Injects Authorization: Bearer <apiKey> on every request the nodes make.
	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '={{ "Bearer " + $credentials.apiKey }}',
			},
		},
	};

	// A cheap authenticated read to validate the credential in the n8n UI.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{ $credentials.apiBaseUrl }}',
			url: '/public/v1/contacts',
			method: 'GET',
			qs: { limit: 1 },
		},
	};
}
